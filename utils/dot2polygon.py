import xml.etree.ElementTree as ET

def dot2polygon(xml_path, group_names, half_box_size, min_spacing, output_path):
    '''
    :param xml_path (str): the path of the annotation file, ex. root\sub_root\filename.xml
    :param group_name (list of str): the list of the name of the groups to be converted to polygon ex. ["lymphocytes", "monocytes"]
    :param half_box_size (list of folat): the list of the size of half of the bbox around the dot in um ex. [4.5, 5.5]
    :param min_spacing (float): the minimum spacing of the wsi corresponding to the annotations ex. 0.25
    :param output_path (str): the output path
    :return:
    '''

    group_names = to_list(group_names)
    half_box_size = to_list(half_box_size)



    # parsing the annotation
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # half_box_size = half_box_size / min_spacing
    half_box_size = [x / min_spacing for x in half_box_size]

    # iterating through the dot annotation.
    for A in root.iter('Annotation'):

        #Lymphocytes:
        for i, group_name in enumerate(group_names):
            if (A.get('PartOfGroup')==group_name) & (A.get('Type')=="Dot"):
            # change the type to Polygon
                A.attrib['Type'] = "Polygon"

                for child in A:
                    for sub_child in child:
                        x_value = sub_child.attrib['X']
                        y_value = sub_child.attrib['Y']
                        sub_child.attrib['X'] = str(float(sub_child.attrib['X'])-half_box_size[i])
                        sub_child.attrib['Y'] = str(float(sub_child.attrib['Y'])-half_box_size[i])
                    child.append(ET.Element(sub_child.tag, Order = '1', X=str(float(x_value)-half_box_size[i]), Y=str(float(y_value)+half_box_size[i])))
                    child.append(ET.Element(sub_child.tag, Order='2', X=str(float(x_value)+half_box_size[i]), Y=str(float(y_value)+half_box_size[i])))
                    child.append(ET.Element(sub_child.tag, Order='3', X=str(float(x_value)+half_box_size[i]), Y=str(float(y_value)-half_box_size[i]) ))



    # writing the new annotation file
    tree.write(output_path)


def to_list(value):
    """Convert value to a list if it's not already a list."""
    return value if isinstance(value, list) else [value]